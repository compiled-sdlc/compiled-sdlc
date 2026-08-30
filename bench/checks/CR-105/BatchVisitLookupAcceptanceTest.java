package org.springframework.samples.petclinic.visits.web;

import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.samples.petclinic.visits.model.Visit;
import org.springframework.samples.petclinic.visits.model.VisitRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static java.util.Arrays.asList;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-105: the batch visit lookup is bounded at one hundred pets.
 *
 * Passability: Count the identifiers in the handler and refuse above the limit before
 * the repository is asked anything. The fixture sends one over the limit and verifies
 * the repository was never called, so refusing after querying does not pass.
 * Confirmed empirically: 12 of 12 cells passed it in the full run.
 */
@WebMvcTest(VisitResource.class)
@ActiveProfiles("test")
class BatchVisitLookupAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VisitRepository visitRepository;

    private String petIds(int count) {
        return IntStream.rangeClosed(1, count)
            .mapToObj(Integer::toString)
            .collect(Collectors.joining(","));
    }

    @Test
    void shouldAnswerAsBeforeAtTheLimit() throws Exception {
        given(visitRepository.findByPetIdIn(anyList()))
            .willReturn(asList(Visit.VisitBuilder.aVisit().id(1).petId(1).build()));

        mvc.perform(get("/pets/visits?petId=" + petIds(100)))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.items[0].id").value(1));
    }

    @Test
    void shouldRejectARequestOverTheLimitWithoutQuerying() throws Exception {
        mvc.perform(get("/pets/visits?petId=" + petIds(101)))
            .andExpect(status().isBadRequest());

        verify(visitRepository, never()).findByPetIdIn(anyList());
    }

    @Test
    void shouldStillAnswerASmallBatch() throws Exception {
        given(visitRepository.findByPetIdIn(asList(111, 222)))
            .willReturn(asList(
                Visit.VisitBuilder.aVisit().id(1).petId(111).build(),
                Visit.VisitBuilder.aVisit().id(2).petId(222).build()));

        mvc.perform(get("/pets/visits?petId=111,222"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.items.length()").value(2));
    }
}
