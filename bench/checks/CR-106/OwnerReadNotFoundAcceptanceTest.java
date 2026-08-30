package org.springframework.samples.petclinic.customers.web;

import java.util.List;
import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.customers.model.Owner;
import org.springframework.samples.petclinic.customers.model.OwnerRepository;
import org.springframework.samples.petclinic.customers.web.mapper.OwnerEntityMapper;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-106: an absent owner is 404, and the success response keeps
 * the shape every existing caller reads.
 *
 * Passability: Make the read handler answer a missing owner as not found rather than an
 * empty body. The fixture stubs findById empty; the module already has an exception
 * mapped to that status.
 * Confirmed empirically: 12 of 12 cells passed it in the full run.
 */
@WebMvcTest(OwnerResource.class)
@ActiveProfiles("test")
class OwnerReadNotFoundAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    OwnerRepository ownerRepository;

    @MockitoBean
    OwnerEntityMapper ownerEntityMapper;

    private Owner anOwner() {
        Owner owner = new Owner();
        owner.setFirstName("George");
        owner.setLastName("Franklin");
        owner.setAddress("110 W. Liberty St.");
        owner.setCity("Madison");
        owner.setTelephone("6085551023");
        return owner;
    }

    @Test
    void shouldAnswerNotFoundForAnOwnerThatDoesNotExist() throws Exception {
        given(ownerRepository.findById(99)).willReturn(Optional.empty());

        mvc.perform(get("/owners/99").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isNotFound());
    }

    @Test
    void shouldStillAnswerTheOwnersFieldsAtTheTopLevel() throws Exception {
        given(ownerRepository.findById(1)).willReturn(Optional.of(anOwner()));

        mvc.perform(get("/owners/1").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.firstName").value("George"))
            .andExpect(jsonPath("$.lastName").value("Franklin"))
            .andExpect(jsonPath("$.city").value("Madison"));
    }

    @Test
    void shouldStillListOwners() throws Exception {
        given(ownerRepository.findAll()).willReturn(List.of(anOwner()));

        mvc.perform(get("/owners").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(1))
            .andExpect(jsonPath("$[0].firstName").value("George"));
    }
}
