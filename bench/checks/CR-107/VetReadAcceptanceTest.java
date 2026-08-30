package org.springframework.samples.petclinic.vets.web;

import java.util.List;
import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.vets.model.Vet;
import org.springframework.samples.petclinic.vets.model.VetRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-107: one vet can be read by identifier.
 *
 * Passability: Add a read handler over the repository's existing findById. The fixture
 * stubs that method, which the pin has, so nothing the agent adds needs to be named by
 * the check.
 * Confirmed empirically: 12 of 12 cells passed it in the full run.
 */
@WebMvcTest(VetResource.class)
@ActiveProfiles("test")
class VetReadAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VetRepository vetRepository;

    private Vet aVet(int id, String firstName, String lastName) {
        Vet vet = new Vet();
        vet.setId(id);
        vet.setFirstName(firstName);
        vet.setLastName(lastName);
        return vet;
    }

    @Test
    void shouldReadOneVetByIdentifier() throws Exception {
        given(vetRepository.findById(2)).willReturn(Optional.of(aVet(2, "Helen", "Leary")));

        mvc.perform(get("/vets/2").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.id").value(2))
            .andExpect(jsonPath("$.firstName").value("Helen"))
            .andExpect(jsonPath("$.lastName").value("Leary"));
    }

    @Test
    void shouldAnswerNotFoundForAVetThatDoesNotExist() throws Exception {
        given(vetRepository.findById(99)).willReturn(Optional.empty());

        mvc.perform(get("/vets/99").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isNotFound());
    }

    @Test
    void shouldStillListVets() throws Exception {
        given(vetRepository.findAll()).willReturn(List.of(aVet(1, "James", "Carter")));

        mvc.perform(get("/vets").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$[0].id").value(1));
    }
}
